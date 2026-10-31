"""
End-to-End integration test validating against the official ground truth benchmark (expected_results.csv).
"""

from pathlib import Path
import pytest
import pandas as pd

from src.ingestion import read_source_file, DEFAULT_INPUT_FILE
from src.validation import classify_records
from src.resolution import resolve_batch
from src.reconciliation import reconcile_run

BASE_DIR = Path(__file__).resolve().parent.parent
EXPECTED_CSV = BASE_DIR / "data" / "expected" / "expected_results.csv"


class TestEndToEndBenchmark:
    def test_complete_vertical_slice_matches_expected_results(self, tmp_path):
        """
        Validates the entire pipeline against source_records.csv and expected_results.csv.
        Asserts 100% agreement on outcome and match_type across all 13 records.
        """
        assert DEFAULT_INPUT_FILE.exists(), f"Input file not found at {DEFAULT_INPUT_FILE}"
        assert EXPECTED_CSV.exists(), f"Expected results file not found at {EXPECTED_CSV}"

        # 1. Read input
        df = read_source_file(DEFAULT_INPUT_FILE)
        assert len(df) == 13
        df["source_record_id"] = range(1, len(df) + 1)
        df["run_id"] = "e2e-benchmark-run"

        # 2. Validation stage
        val_results = classify_records(df)
        val_df = pd.DataFrame(val_results)
        df["validation_status"] = val_df["validation_status"]
        df["validation_reason"] = val_df["validation_reason"]

        # 3. Resolution stage
        resolved = resolve_batch(
            df_all=df,
            run_id="e2e-benchmark-run",
            existing_canonicals=pd.DataFrame(),
            starting_canonical_seq=1001
        )
        res_df = pd.DataFrame(resolved["reconciliation_results"])
        assert len(res_df) == 13

        # 4. Compare with expected ground truth
        expected_df = pd.read_csv(EXPECTED_CSV)
        assert len(expected_df) == 13

        for i in range(13):
            exp_row = expected_df.iloc[i]
            act_row = res_df.iloc[i]

            exp_sys = str(exp_row["source_system"]).strip() if pd.notna(exp_row["source_system"]) else None
            act_sys = str(act_row["source_system"]).strip() if act_row["source_system"] else None
            assert exp_sys == act_sys, f"Row {i+1} source_system mismatch: {exp_sys} != {act_sys}"

            exp_id = str(exp_row["source_id"]).strip() if pd.notna(exp_row["source_id"]) else None
            act_id = str(act_row["source_id"]).strip() if act_row["source_id"] else None
            assert exp_id == act_id, f"Row {i+1} source_id mismatch: {exp_id} != {act_id}"

            assert act_row["outcome"] == exp_row["expected_outcome"], (
                f"Row {i+1} outcome mismatch: {act_row['outcome']} != {exp_row['expected_outcome']}"
            )
            assert act_row["match_type"] == exp_row["expected_match_type"], (
                f"Row {i+1} match_type mismatch: {act_row['match_type']} != {exp_row['expected_match_type']}"
            )

        # 5. Reconciliation & conservation check
        summary = reconcile_run(
            run_id="e2e-benchmark-run",
            reconciliation_df=res_df,
            output_dir=tmp_path,
            report_dir=tmp_path
        )
        assert summary["is_balanced"] is True
        assert summary["total_records"] == 13
        assert summary["accounted_for"] == 13
        assert summary["benchmark"]["accuracy_percentage"] == 100.0

