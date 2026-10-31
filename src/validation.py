"""
Data Validation Module for Entity Resolution Pipeline.

Applies data-quality rules to each source record:
  VALID      - passes all checks, eligible for resolution.
  REJECTED   - fails a hard rule (missing key, malformed email, conflicting duplicate).
  DUPLICATE  - exact repeat of a source key already seen in this batch.
  UNRESOLVED - structurally valid but lacks sufficient identity attributes (no email AND no phone).
Results are persisted to record_validation, data_quality_rejects, and unresolved_mappings.
"""

import re
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any

import pandas as pd

from src.store import get_connection, DEFAULT_DB_PATH
from src.normalization import normalize_email, normalize_phone

logger = logging.getLogger(__name__)

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


def validate_email_syntax(email: Any) -> bool:
    if not email or pd.isna(email):
        return False
    return bool(EMAIL_REGEX.match(str(email).strip()))


def classify_records(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    Classify each record in df. Returns list of dicts with keys:
      source_record_id, run_id, validation_status, validation_reason
    """
    if df.empty:
        return []

    results = []
    seen_keys: Dict[str, Dict] = {}  # (source_system, source_id) -> first record

    for _, row in df.iterrows():
        src_id_raw = row.get("source_id")
        src_sys_raw = row.get("source_system")
        email_raw = row.get("email")
        phone_raw = row.get("phone")

        record_id = row.get("source_record_id", None)
        run_id = row.get("run_id", None)

        src_sys = str(src_sys_raw).strip() if src_sys_raw and str(src_sys_raw).strip() else None
        src_id = str(src_id_raw).strip() if src_id_raw and str(src_id_raw).strip() else None

        # Rule 1: source_system required
        if not src_sys:
            results.append({"source_record_id": record_id, "run_id": run_id,
                            "validation_status": "REJECTED", "validation_reason": "missing_source_system"})
            continue

        # Rule 2: source_id required
        if not src_id:
            results.append({"source_record_id": record_id, "run_id": run_id,
                            "validation_status": "REJECTED", "validation_reason": "missing_source_id"})
            continue

        # Rule 3: email format check (if email is present)
        if email_raw and str(email_raw).strip():
            norm_email = normalize_email(email_raw)
            if norm_email and not validate_email_syntax(norm_email):
                results.append({"source_record_id": record_id, "run_id": run_id,
                                "validation_status": "REJECTED", "validation_reason": "invalid_email"})
                continue

        # Rule 4: duplicate key detection
        composite_key = (src_sys, src_id)
        if composite_key in seen_keys:
            first = seen_keys[composite_key]
            # Check if data is identical (true duplicate) or conflicting
            same_email = normalize_email(email_raw) == normalize_email(first.get("email"))
            same_phone = normalize_phone(phone_raw) == normalize_phone(first.get("phone"))
            if same_email and same_phone:
                results.append({"source_record_id": record_id, "run_id": run_id,
                                "validation_status": "DUPLICATE", "validation_reason": "duplicate_source_key"})
            else:
                # Conflicting duplicate: reject BOTH
                # Update the first record's status
                for r in results:
                    if r["source_record_id"] == first["source_record_id"]:
                        r["validation_status"] = "REJECTED"
                        r["validation_reason"] = "conflicting_duplicate_source_key"
                        break
                results.append({"source_record_id": record_id, "run_id": run_id,
                                "validation_status": "REJECTED", "validation_reason": "conflicting_duplicate_source_key"})
            continue

        seen_keys[composite_key] = dict(row)
        seen_keys[composite_key]["source_record_id"] = record_id

        # Rule 5: unresolved - no email AND no phone
        has_email = bool(email_raw and str(email_raw).strip() and validate_email_syntax(normalize_email(email_raw) or ""))
        has_phone = bool(phone_raw and normalize_phone(phone_raw))
        if not has_email and not has_phone:
            results.append({"source_record_id": record_id, "run_id": run_id,
                            "validation_status": "UNRESOLVED", "validation_reason": "no_identifiers"})
            continue

        results.append({"source_record_id": record_id, "run_id": run_id,
                        "validation_status": "VALID", "validation_reason": None})

    return results


def save_validation_results(results: List[Dict[str, Any]], run_id: str, db_path: Optional[Path] = None):
    """Persist classification results to SQLite."""
    if not results:
        return

    rejects, unresolved = [], []
    for r in results:
        if r["validation_status"] in ("REJECTED", "DUPLICATE"):
            rejects.append((r["source_record_id"], run_id, r["validation_reason"] or "UNKNOWN"))
        elif r["validation_status"] == "UNRESOLVED":
            unresolved.append((r["source_record_id"], run_id, r["validation_reason"] or "UNKNOWN"))

    conn = get_connection(db_path)
    try:
        with conn:
            conn.executemany(
                "INSERT INTO record_validation (source_record_id, run_id, validation_status, validation_reason) VALUES (?,?,?,?)",
                [(r["source_record_id"], run_id, r["validation_status"], r["validation_reason"]) for r in results],
            )
            if rejects:
                conn.executemany(
                    "INSERT INTO data_quality_rejects (source_record_id, run_id, rejection_reason) VALUES (?,?,?)",
                    rejects,
                )
            if unresolved:
                conn.executemany(
                    "INSERT INTO unresolved_mappings (source_record_id, run_id, reason) VALUES (?,?,?)",
                    unresolved,
                )
            rejected_cnt = sum(1 for r in results if r["validation_status"] == "REJECTED")
            dup_cnt = sum(1 for r in results if r["validation_status"] == "DUPLICATE")
            unres_cnt = len(unresolved)
            conn.execute(
                "UPDATE pipeline_runs SET rejected_count=?, unresolved_count=? WHERE run_id=?",
                (rejected_cnt + dup_cnt, unres_cnt, run_id),
            )
    finally:
        conn.close()


def load_source_records(run_id: str, db_path: Optional[Path] = None) -> pd.DataFrame:
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM source_records WHERE run_id=? ORDER BY source_record_id", (run_id,)
        ).fetchall()
        return pd.DataFrame([dict(r) for r in rows])
    finally:
        conn.close()


def run_validation(run_id: str, db_path: Optional[Path] = None) -> Dict[str, Any]:
    """Execute validation stage for a given run_id."""
    logger.info("Validating run %s", run_id)

    # Idempotency: skip if already validated
    conn = get_connection(db_path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM record_validation WHERE run_id=?", (run_id,)).fetchone()[0]
    finally:
        conn.close()

    if count > 0:
        logger.info("Run %s already validated (%d records). Skipping.", run_id, count)
        return {"run_id": run_id, "status": "SKIPPED"}

    df = load_source_records(run_id, db_path)
    results = classify_records(df)
    save_validation_results(results, run_id, db_path)

    summary = pd.DataFrame(results)["validation_status"].value_counts().to_dict() if results else {}
    return {"run_id": run_id, "status": "SUCCESS", "total_records": len(results), "breakdown": summary}
