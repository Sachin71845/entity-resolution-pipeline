"""
Reconciliation & Reporting Module for Entity Resolution Pipeline.

Verifies end-to-end data conservation:
  Total Input = New Entities + Mapped + Conflicts + Unresolved + Duplicates + Rejects

Exports:
  - data/output/resolution_results_{run_id}.csv
  - reports/reconciliation_report_{run_id}.md
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

import pandas as pd

from src.store import get_connection

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = BASE_DIR / "data" / "output"
DEFAULT_REPORT_DIR = BASE_DIR / "reports"
EXPECTED_RESULTS_FILE = BASE_DIR / "data" / "expected" / "expected_results.csv"

logger = logging.getLogger(__name__)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def reconcile_run(
    run_id: str,
    reconciliation_df: pd.DataFrame,
    output_dir: Optional[Path] = None,
    report_dir: Optional[Path] = None,
    db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Compute conservation check, export CSV, and write Markdown report."""
    out_dir = Path(output_dir or DEFAULT_OUTPUT_DIR)
    rep_dir = Path(report_dir or DEFAULT_REPORT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    rep_dir.mkdir(parents=True, exist_ok=True)

    total_records = len(reconciliation_df)
    new_entity_count = int((reconciliation_df["outcome"] == "NEW_ENTITY").sum())
    mapped_count = int((reconciliation_df["outcome"] == "MAPPED").sum())
    conflict_count = int((reconciliation_df["outcome"] == "CONFLICT").sum())
    unresolved_count = int((reconciliation_df["outcome"] == "UNRESOLVED").sum())
    duplicate_count = int((reconciliation_df["outcome"] == "DUPLICATE").sum())
    rejected_count = int((reconciliation_df["outcome"] == "REJECTED").sum())

    accounted_for = new_entity_count + mapped_count + conflict_count + unresolved_count + duplicate_count + rejected_count
    discrepancy = total_records - accounted_for
    is_balanced = discrepancy == 0

    # Benchmark comparison
    benchmark_comparison = None
    if EXPECTED_RESULTS_FILE.exists():
        try:
            expected_df = pd.read_csv(EXPECTED_RESULTS_FILE)
            matches = 0
            for i in range(min(len(expected_df), len(reconciliation_df))):
                if (reconciliation_df.iloc[i]["outcome"] == expected_df.iloc[i]["expected_outcome"] and
                        reconciliation_df.iloc[i]["match_type"] == expected_df.iloc[i]["expected_match_type"]):
                    matches += 1
            benchmark_comparison = {
                "total_benchmark_records": len(expected_df),
                "matched_records": matches,
                "accuracy_percentage": (matches / len(expected_df)) * 100.0,
            }
        except Exception as exc:
            logger.warning("Could not compare with expected benchmark: %s", exc)

    # Export CSV
    export_cols = ["source_system", "source_id", "outcome", "match_type", "canonical_id", "confidence_score"]
    run_csv = out_dir / f"resolution_results_{run_id}.csv"
    latest_csv = out_dir / "resolution_results.csv"
    reconciliation_df[export_cols].to_csv(run_csv, index=False)
    reconciliation_df[export_cols].to_csv(latest_csv, index=False)

    # Markdown report
    match_type_md = ""
    for m_type, cnt in reconciliation_df["match_type"].value_counts().items():
        match_type_md += f"| `{m_type}` | {cnt} |\n"

    row_detail_md = ""
    for _, row in reconciliation_df.iterrows():
        c_id = row["canonical_id"] if row["canonical_id"] else "—"
        conf = f"{row['confidence_score']:.1f}%" if pd.notna(row.get("confidence_score")) and row["confidence_score"] is not None else "—"
        row_detail_md += f"| {row['source_system']} | {row['source_id']} | `{row['outcome']}` | `{row['match_type']}` | `{c_id}` | {conf} |\n"

    benchmark_md = ""
    if benchmark_comparison:
        benchmark_md = f"""
---

## 3. Ground Truth Benchmark Verification

| Metric | Value |
| :--- | :--- |
| Benchmark File | `{EXPECTED_RESULTS_FILE.name}` |
| Total Records | `{benchmark_comparison['total_benchmark_records']}` |
| Matched Exactly | `{benchmark_comparison['matched_records']}` |
| **Accuracy Score** | **`{benchmark_comparison['accuracy_percentage']:.1f}%`** |
"""

    report_content = f"""# Entity Resolution Reconciliation Report

**Run ID:** `{run_id}`
**Generated At:** `{utc_now()}`
**Reconciliation Status:** `{'BALANCED — 100% Accounted' if is_balanced else 'DISCREPANCY DETECTED'}`

---

## 1. Conservation of Records

| Category | Count | % |
| :--- | :---: | :---: |
| New Golden Records | {new_entity_count} | {new_entity_count/total_records*100 if total_records else 0:.1f}% |
| Deterministic Matches | {mapped_count} | {mapped_count/total_records*100 if total_records else 0:.1f}% |
| Mapping Conflicts | {conflict_count} | {conflict_count/total_records*100 if total_records else 0:.1f}% |
| Unresolved | {unresolved_count} | {unresolved_count/total_records*100 if total_records else 0:.1f}% |
| Duplicate Source Keys | {duplicate_count} | {duplicate_count/total_records*100 if total_records else 0:.1f}% |
| Data Quality Rejects | {rejected_count} | {rejected_count/total_records*100 if total_records else 0:.1f}% |
| **Total Accounted** | **{accounted_for}** | **100%** |
| **Total Input** | **{total_records}** | — |

**Discrepancy:** `{discrepancy}` records.

---

## 2. Match Type Breakdown

| Match Type | Count |
| :--- | :---: |
{match_type_md}
{benchmark_md}

---

## 4. Record-Level Detail

| Source System | Source ID | Outcome | Match Type | Canonical ID | Confidence |
| :--- | :--- | :--- | :--- | :--- | :---: |
{row_detail_md}
"""

    run_report = rep_dir / f"reconciliation_report_{run_id}.md"
    latest_report = rep_dir / "latest_reconciliation.md"
    run_report.write_text(report_content, encoding="utf-8")
    latest_report.write_text(report_content, encoding="utf-8")

    logger.info("Reconciliation report: %s  |  CSV: %s", run_report.name, run_csv.name)

    return {
        "run_id": run_id,
        "total_records": total_records,
        "accounted_for": accounted_for,
        "is_balanced": is_balanced,
        "discrepancy": discrepancy,
        "new_entities": new_entity_count,
        "mapped": mapped_count,
        "conflicts": conflict_count,
        "unresolved": unresolved_count,
        "duplicates": duplicate_count,
        "rejected": rejected_count,
        "output_csv": str(run_csv),
        "report_md": str(run_report),
        "benchmark": benchmark_comparison,
    }
