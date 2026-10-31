"""
Performance Measurement & Benchmarking Module for Entity Resolution.

Evaluates pipeline processing throughput (records/second) and latency across
varying dataset scales (e.g. 500, 2,500, 10,000 records).

Identifies key architectural optimizations for enterprise-scale execution.
"""

import time
import argparse
import logging
from typing import List, Dict, Any

import pandas as pd

from src.data_generator import generate_synthetic_records
from src.normalization import normalize_dataframe
from src.validation import classify_records
from src.resolution import resolve_batch
from src.reconciliation import reconcile_run

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("benchmark")


def benchmark_scale(
    record_count: int,
    seed: int = 42
) -> Dict[str, Any]:
    """
    Benchmark pipeline execution latency and throughput for a specific record volume.
    """
    logger.info("Generating %d records for benchmark (seed=%d)...", record_count, seed)
    df_raw = generate_synthetic_records(total_records=record_count, seed=seed)
    df_raw["source_record_id"] = range(1, len(df_raw) + 1)
    df_raw["run_id"] = f"benchmark-{record_count}"

    start_total = time.perf_counter()

    # 1. Normalization Stage
    t0 = time.perf_counter()
    df_norm = normalize_dataframe(df_raw)
    norm_duration = time.perf_counter() - t0

    # 2. Validation Stage
    t1 = time.perf_counter()
    val_results = classify_records(df_norm)
    val_df = pd.DataFrame(val_results)
    df_norm["validation_status"] = val_df["validation_status"]
    df_norm["validation_reason"] = val_df["validation_reason"]
    val_duration = time.perf_counter() - t1

    # 3. Resolution & Matching Stage
    t2 = time.perf_counter()
    resolved = resolve_batch(
        df_all=df_norm,
        run_id=f"benchmark-{record_count}",
        existing_canonicals=pd.DataFrame(),
        starting_canonical_seq=1001
    )
    res_duration = time.perf_counter() - t2

    # 4. Reconciliation Stage
    t3 = time.perf_counter()
    res_df = pd.DataFrame(resolved["reconciliation_results"])
    # In-memory reconciliation check
    total = len(res_df)
    counts = res_df["outcome"].value_counts().to_dict()
    recon_duration = time.perf_counter() - t3

    total_duration = time.perf_counter() - start_total
    throughput = record_count / total_duration if total_duration > 0 else 0.0

    return {
        "record_count": record_count,
        "total_duration_sec": total_duration,
        "throughput_rec_per_sec": throughput,
        "norm_duration_sec": norm_duration,
        "val_duration_sec": val_duration,
        "res_duration_sec": res_duration,
        "recon_duration_sec": recon_duration,
        "new_entities": counts.get("NEW_ENTITY", 0),
        "mapped": counts.get("MAPPED", 0),
        "conflicts": counts.get("CONFLICT", 0),
        "unresolved": counts.get("UNRESOLVED", 0),
        "duplicates": counts.get("DUPLICATE", 0),
        "rejected": counts.get("REJECTED", 0)
    }


def run_benchmarks(scales: List[int]) -> pd.DataFrame:
    """Run benchmark across multiple record volumes and display summary."""
    print("=" * 80)
    print("           ENTITY RESOLUTION PIPELINE PERFORMANCE BENCHMARK")
    print("=" * 80)

    results = []
    for count in scales:
        print(f"\n[Running Benchmark] Volume: {count:,} records...")
        res = benchmark_scale(count)
        results.append(res)
        print(f"  Total Duration:  {res['total_duration_sec']:.4f} s")
        print(f"  Throughput:      {res['throughput_rec_per_sec']:,.1f} records/second")
        print(f"  Breakdown:       Norm: {res['norm_duration_sec']:.4f}s | "
              f"Val: {res['val_duration_sec']:.4f}s | "
              f"Res: {res['res_duration_sec']:.4f}s | "
              f"Recon: {res['recon_duration_sec']:.4f}s")

    df_summary = pd.DataFrame(results)

    print("\n" + "=" * 80)
    print("                           BENCHMARK SUMMARY")
    print("=" * 80)
    display_cols = [
        "record_count",
        "total_duration_sec",
        "throughput_rec_per_sec",
        "val_duration_sec",
        "res_duration_sec"
    ]
    print(df_summary[display_cols].to_string(index=False))
    print("=" * 80)

    print("\n--- ARCHITECTURAL OPTIMIZATION NOTES ---")
    print("1. In-Memory Hash Indices: Using dictionary lookups for exact email and (name, phone)")
    print("   reduces comparison complexity from O(N^2) pairwise comparisons to O(N) average time.")
    print("2. pyodbc fast_executemany: When inserting to MSSQL, fast_executemany=True batches rows")
    print("   into parameterized tabular data stream (TDS) arrays, reducing network roundtrips by 25-50x.")
    print("3. Blocking Candidate Pairs: For scaling beyond 1,000,000+ records, blocking/canopy clustering")
    print("   on phonetics (Double Metaphone / Soundex) or email domain partitions candidates cleanly.")
    print("=" * 80)

    return df_summary


def main():
    parser = argparse.ArgumentParser(
        description="Run performance measurement benchmark on Entity Resolution pipeline."
    )
    parser.add_argument(
        "--scales",
        type=int,
        nargs="+",
        default=[500, 2500, 10000],
        help="List of record volumes to test (default: 500 2500 10000)"
    )
    args = parser.parse_args()
    run_benchmarks(args.scales)


if __name__ == "__main__":
    main()

