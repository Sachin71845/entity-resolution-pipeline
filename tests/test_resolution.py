"""
Unit tests for resolution engine (src/resolution.py) and reconciliation (src/reconciliation.py).
"""

from pathlib import Path
import pytest
import pandas as pd

from src.resolution import resolve_batch, detect_conflicts
from src.reconciliation import reconcile_run


class TestResolutionLogic:
    def test_new_entity_creation(self):
        df = pd.DataFrame([{
            "source_record_id": 1,
            "run_id": "test-run",
            "source_system": "CRM",
            "source_id": "C101",
            "full_name": "Sachin Jadhav",
            "email": "sachin@gmail.com",
            "phone": "9876543210",
            "validation_status": "VALID",
            "validation_reason": None
        }])
        resolved = resolve_batch(df, "test-run", existing_canonicals=pd.DataFrame(), starting_canonical_seq=1001)
        res_list = resolved["reconciliation_results"]
        assert len(res_list) == 1
        assert res_list[0]["outcome"] == "NEW_ENTITY"
        assert res_list[0]["match_type"] == "new"
        assert res_list[0]["canonical_id"] == "CAN-1001"
        assert res_list[0]["confidence_score"] == 100.0

    def test_exact_email_match(self):
        df = pd.DataFrame([
            {
                "source_record_id": 1,
                "run_id": "test-run",
                "source_system": "CRM",
                "source_id": "C101",
                "full_name": "Sachin Jadhav",
                "email": "sachin@gmail.com",
                "phone": "9876543210",
                "validation_status": "VALID",
                "validation_reason": None
            },
            {
                "source_record_id": 2,
                "run_id": "test-run",
                "source_system": "ECOM",
                "source_id": "E501",
                "full_name": "Sachin Jadhav",
                "email": "sachin@gmail.com",
                "phone": "9876543210",
                "validation_status": "VALID",
                "validation_reason": None
            }
        ])
        resolved = resolve_batch(df, "test-run", existing_canonicals=pd.DataFrame(), starting_canonical_seq=1001)
        res_list = resolved["reconciliation_results"]
        assert res_list[0]["outcome"] == "NEW_ENTITY"
        assert res_list[1]["outcome"] == "MAPPED"
        assert res_list[1]["match_type"] == "exact_email"
        assert res_list[1]["canonical_id"] == res_list[0]["canonical_id"]

    def test_exact_email_after_normalization(self):
        df = pd.DataFrame([
            {
                "source_record_id": 1,
                "run_id": "test-run",
                "source_system": "CRM",
                "source_id": "C101",
                "full_name": "Sachin Jadhav",
                "email": "sachin@gmail.com",
                "phone": "9876543210",
                "validation_status": "VALID",
                "validation_reason": None
            },
            {
                "source_record_id": 2,
                "run_id": "test-run",
                "source_system": "MARKETING",
                "source_id": "M901",
                "full_name": "Sachin Jadhav",
                "email": "SACHIN@GMAIL.COM",
                "phone": "9876543210",
                "validation_status": "VALID",
                "validation_reason": None
            }
        ])
        resolved = resolve_batch(df, "test-run", existing_canonicals=pd.DataFrame(), starting_canonical_seq=1001)
        res_list = resolved["reconciliation_results"]
        assert res_list[1]["outcome"] == "MAPPED"
        assert res_list[1]["match_type"] == "exact_email_after_normalization"
        assert res_list[1]["canonical_id"] == "CAN-1001"

    def test_secondary_rule_match_name_and_phone(self):
        df = pd.DataFrame([
            {
                "source_record_id": 1,
                "run_id": "test-run",
                "source_system": "CRM",
                "source_id": "C102",
                "full_name": "Rahul Patil",
                "email": "rahul@gmail.com",
                "phone": "9123456780",
                "validation_status": "VALID",
                "validation_reason": None
            },
            {
                "source_record_id": 2,
                "run_id": "test-run",
                "source_system": "ECOM",
                "source_id": "E502",
                "full_name": "Rahul Patil",
                "email": "rahul.patil@gmail.com",  # Different email!
                "phone": "9123456780",           # Same phone & name
                "validation_status": "VALID",
                "validation_reason": None
            }
        ])
        resolved = resolve_batch(df, "test-run", existing_canonicals=pd.DataFrame(), starting_canonical_seq=1001)
        res_list = resolved["reconciliation_results"]
        assert res_list[0]["outcome"] == "NEW_ENTITY"
        assert res_list[1]["outcome"] == "MAPPED"
        assert res_list[1]["match_type"] == "rule_name_phone"
        assert res_list[1]["canonical_id"] == res_list[0]["canonical_id"]
        assert res_list[1]["confidence_score"] == 90.0

    def test_domain_edge_case_email_collision_and_multiple_candidates(self):
        df = pd.DataFrame([
            {
                "source_record_id": 1,
                "run_id": "test-run",
                "source_system": "CRM",
                "source_id": "C201",
                "full_name": "Asha Kulkarni",
                "email": "shared@gmail.com",
                "phone": "9000000001",
                "validation_status": "VALID",
                "validation_reason": None
            },
            {
                "source_record_id": 2,
                "run_id": "test-run",
                "source_system": "CRM",
                "source_id": "C202",
                "full_name": "Neha Joshi",
                "email": "shared@gmail.com",
                "phone": "9000000002",
                "validation_status": "VALID",
                "validation_reason": None
            },
            {
                "source_record_id": 3,
                "run_id": "test-run",
                "source_system": "ECOM",
                "source_id": "E901",
                "full_name": "Unknown Customer",
                "email": "shared@gmail.com",
                "phone": "9000000003",
                "validation_status": "VALID",
                "validation_reason": None
            }
        ])
        resolved = resolve_batch(df, "test-run", existing_canonicals=pd.DataFrame(), starting_canonical_seq=1001)
        res_list = resolved["reconciliation_results"]
        assert res_list[0]["outcome"] == "CONFLICT"
        assert res_list[0]["match_type"] == "email_collision"
        assert res_list[1]["outcome"] == "CONFLICT"
        assert res_list[1]["match_type"] == "email_collision"
        assert res_list[2]["outcome"] == "CONFLICT"
        assert res_list[2]["match_type"] == "multiple_candidates"

    def test_empty_resolution_batch(self):
        df = pd.DataFrame(columns=[
            "source_record_id", "run_id", "source_system", "source_id",
            "full_name", "email", "phone", "validation_status", "validation_reason"
        ])
        resolved = resolve_batch(df, "test-run", existing_canonicals=pd.DataFrame(), starting_canonical_seq=1001)
        assert resolved["reconciliation_results"] == []
        assert resolved["mapped_count"] == 0
        assert resolved["conflict_count"] == 0


class TestReconciliationMath:
    def test_conservation_of_records(self, tmp_path):
        data = [
            {"source_record_id": 1, "source_system": "CRM", "source_id": "C1", "outcome": "NEW_ENTITY", "match_type": "new", "canonical_id": "CAN-1001", "confidence_score": 100.0},
            {"source_record_id": 2, "source_system": "ECOM", "source_id": "E1", "outcome": "MAPPED", "match_type": "exact_email", "canonical_id": "CAN-1001", "confidence_score": 100.0},
            {"source_record_id": 3, "source_system": "CRM", "source_id": "C2", "outcome": "CONFLICT", "match_type": "email_collision", "canonical_id": None, "confidence_score": None},
            {"source_record_id": 4, "source_system": "CRM", "source_id": "C3", "outcome": "UNRESOLVED", "match_type": "no_identifiers", "canonical_id": None, "confidence_score": None},
            {"source_record_id": 5, "source_system": "CRM", "source_id": "C1", "outcome": "DUPLICATE", "match_type": "duplicate_source_key", "canonical_id": None, "confidence_score": None},
            {"source_record_id": 6, "source_system": "ECOM", "source_id": "E2", "outcome": "REJECTED", "match_type": "invalid_email", "canonical_id": None, "confidence_score": None},
        ]
        df = pd.DataFrame(data)
        summary = reconcile_run("test-run-recon", df, output_dir=tmp_path, report_dir=tmp_path)
        assert summary["is_balanced"] is True
        assert summary["total_records"] == 6
        assert summary["accounted_for"] == 6
        assert summary["discrepancy"] == 0
        assert (tmp_path / "resolution_results_test-run-recon.csv").exists()
        assert (tmp_path / "reconciliation_report_test-run-recon.md").exists()

