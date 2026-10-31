"""
Data Ingestion Module for Entity Resolution Pipeline.

Responsibilities:
1. SHA-256 file hashing for idempotency (same file → same run skipped).
2. Load and schema-validate raw CSV batches.
3. Register pipeline run in SQLite pipeline_runs table.
4. Bulk-insert raw records into source_records table.
"""

import uuid
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any

import pandas as pd

from src.store import get_connection, init_db, DEFAULT_DB_PATH

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_FILE = BASE_DIR / "data" / "input" / "source_records.csv"

EXPECTED_COLUMNS = [
    "source_system",
    "source_id",
    "full_name",
    "email",
    "phone",
    "source_updated_at",
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_run_id() -> str:
    return str(uuid.uuid4())


def calculate_file_hash(file_path: Path) -> str:
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def read_source_file(file_path: Path) -> pd.DataFrame:
    if not file_path.exists():
        raise FileNotFoundError(f"Source file not found at: {file_path}")
    df = pd.read_csv(file_path, dtype=str, encoding="utf-8-sig", keep_default_na=False)
    df.columns = df.columns.str.strip()
    missing = set(EXPECTED_COLUMNS) - set(df.columns)
    unexpected = set(df.columns) - set(EXPECTED_COLUMNS)
    if missing or unexpected:
        raise ValueError(
            f"Schema mismatch in {file_path.name}. Missing: {missing}. Unexpected: {unexpected}."
        )
    df = df[EXPECTED_COLUMNS].copy()
    df = df.map(lambda x: None if (isinstance(x, str) and not x.strip()) else x)
    logger.info("Loaded %d records from %s", len(df), file_path.name)
    return df


def check_existing_batch(file_hash: str, db_path: Optional[Path] = None) -> Optional[str]:
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT run_id FROM pipeline_runs WHERE source_file_hash=? AND run_status='SUCCESS' LIMIT 1",
            (file_hash,),
        ).fetchone()
        return row["run_id"] if row else None
    finally:
        conn.close()


def run_ingestion(
    input_path: Optional[Path] = None,
    force: bool = False,
    db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    file_path = Path(input_path or DEFAULT_INPUT_FILE)
    init_db(db_path)

    file_hash = calculate_file_hash(file_path)

    if not force:
        existing_run = check_existing_batch(file_hash, db_path)
        if existing_run:
            logger.info("Batch already processed. Run ID: %s  (use --force to rerun)", existing_run)
            return {"status": "SKIPPED", "run_id": existing_run, "reason": "already_processed"}

    df = read_source_file(file_path)
    run_id = generate_run_id()
    start = utc_now()

    records = []
    for _, row in df.iterrows():
        records.append((
            run_id,
            row.get("source_system"),
            row.get("source_id"),
            row.get("full_name"),
            row.get("email"),
            row.get("phone"),
            row.get("source_updated_at"),
            str(file_path),
            start,
        ))

    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """INSERT INTO pipeline_runs
                   (run_id, source_file, source_file_hash, start_time, run_status, input_count, processed_count)
                   VALUES (?, ?, ?, ?, 'RUNNING', ?, ?)""",
                (run_id, str(file_path), file_hash, start, len(df), len(df)),
            )
            conn.executemany(
                """INSERT INTO source_records
                   (run_id, source_system, source_id, full_name, email, phone, source_updated_at, source_file, ingested_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                records,
            )
    finally:
        conn.close()

    logger.info("Ingested %d records for Run ID %s", len(df), run_id)
    return {"status": "STARTED", "run_id": run_id, "record_count": len(df)}
