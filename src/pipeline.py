"""
Master Pipeline Orchestrator for Entity Resolution.

Coordinates the end-to-end lifecycle:
1. Ingestion   -> SHA-256 idempotency + raw record staging
2. Validation  -> data-quality classification + quarantine
3. Resolution  -> deterministic matching + conflict detection
4. Reconciliation -> conservation check + reports
"""

import sys
import time
import argparse
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from src.store import init_db, DEFAULT_DB_PATH
from src.ingestion import run_ingestion, DEFAULT_INPUT_FILE
from src.validation import run_validation
from src.resolution import run_resolution
from src.reconciliation import reconcile_run

BASE_DIR = Path(__file__).resolve().parent.parent

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("pipeline")


def run_pipeline(
    input_path: Optional[Path] = None,
    force: bool = False,
    output_dir: Optional[Path] = None,
    report_dir: Optional[Path] = None,
    db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Execute the complete Entity Resolution Pipeline end-to-end."""
    start_time = time.time()
    target_file = Path(input_path or DEFAULT_INPUT_FILE)
    db = Path(db_path or DEFAULT_DB_PATH)

    print("=" * 70)
    print("       ENTITY RESOLUTION PIPELINE — EXECUTION START")
    print("=" * 70)
    print(f"Input File : {target_file}")
    print(f"Database   : {db}")
    print(f"Force Rerun: {force}")

    # Bootstrap schema
    init_db(db)

    # Step 1: Ingestion
    print("\n[STEP 1/4] INGESTION")
    print("-" * 50)
    ingest_result = run_ingestion(input_path=target_file, force=force, db_path=db)

    if ingest_result["status"] == "SKIPPED":
        print(f"\n[INFO] Batch already processed. Run ID: {ingest_result['run_id']}")
        print("Use --force to re-process.")
        return {"status": "SKIPPED", "run_id": ingest_result["run_id"]}

    run_id = ingest_result["run_id"]
    print(f"Run ID     : {run_id}")
    print(f"Records    : {ingest_result['record_count']}")

    # Step 2: Validation
    print("\n[STEP 2/4] DATA QUALITY VALIDATION")
    print("-" * 50)
    val_result = run_validation(run_id=run_id, db_path=db)
    print(f"Classified : {val_result.get('total_records', 0)} records")
    print(f"Breakdown  : {val_result.get('breakdown', {})}")

    # Step 3: Resolution
    print("\n[STEP 3/4] ENTITY RESOLUTION & MATCHING")
    print("-" * 50)
    recon_df = run_resolution(run_id=run_id, db_path=db)
    print(f"Resolved   : {len(recon_df)} records")

    # Step 4: Reconciliation
    print("\n[STEP 4/4] RECONCILIATION & REPORTING")
    print("-" * 50)
    rec_summary = reconcile_run(
        run_id=run_id,
        reconciliation_df=recon_df,
        output_dir=output_dir,
        report_dir=report_dir,
        db_path=db,
    )

    elapsed = time.time() - start_time

    print("\n" + "=" * 70)
    print("                PIPELINE RUN SUMMARY")
    print("=" * 70)
    print(f"Run ID              : {run_id}")
    print(f"Elapsed Time        : {elapsed:.2f} s")
    print(f"Reconciliation      : {'BALANCED' if rec_summary['is_balanced'] else 'DISCREPANCY DETECTED'}")
    print(f"Total Input         : {rec_summary['total_records']}")
    print(f"  -> New Entities   : {rec_summary['new_entities']}")
    print(f"  -> Mapped         : {rec_summary['mapped']}")
    print(f"  -> Conflicts      : {rec_summary['conflicts']}")
    print(f"  -> Unresolved     : {rec_summary['unresolved']}")
    print(f"  -> Duplicates     : {rec_summary['duplicates']}")
    print(f"  -> Rejects        : {rec_summary['rejected']}")

    if rec_summary.get("benchmark"):
        bm = rec_summary["benchmark"]
        print(f"\nBenchmark           : {bm['matched_records']}/{bm['total_benchmark_records']} "
              f"({bm['accuracy_percentage']:.1f}% Accuracy)")

    print(f"\nOutput CSV          : {rec_summary['output_csv']}")
    print(f"Audit Report        : {rec_summary['report_md']}")
    print("=" * 70)

    return {
        "status": "SUCCESS",
        "run_id": run_id,
        "elapsed_seconds": elapsed,
        "reconciliation": rec_summary,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Run Entity Resolution Pipeline on source data."
    )
    parser.add_argument(
        "--input", "-i",
        type=str,
        default=None,
        help="Path to source CSV records (default: data/input/source_records.csv)"
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Force re-execution of a batch that was previously processed."
    )
    parser.add_argument(
        "--db",
        type=str,
        default=None,
        help="Path to SQLite database file (default: data/pipeline.db)"
    )
    parser.add_argument(
        "--output-dir", "-o",
        type=str,
        default=None,
        help="Directory to save output CSV datasets (default: data/output)"
    )
    parser.add_argument(
        "--report-dir", "-r",
        type=str,
        default=None,
        help="Directory to save Markdown audit reports (default: reports)"
    )

    args = parser.parse_args()

    input_path = Path(args.input) if args.input else None
    output_dir = Path(args.output_dir) if args.output_dir else None
    report_dir = Path(args.report_dir) if args.report_dir else None
    db_path = Path(args.db) if args.db else None

    try:
        run_pipeline(
            input_path=input_path,
            force=args.force,
            output_dir=output_dir,
            report_dir=report_dir,
            db_path=db_path,
        )
    except Exception as error:
        logger.exception("Pipeline execution failed: %s", error)
        sys.exit(1)


if __name__ == "__main__":
    main()
