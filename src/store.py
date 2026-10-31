"""
Local SQLite storage layer for Entity Resolution Pipeline.

Provides the same logical schema as database/schema.sql but using
Python's built-in sqlite3 module - zero external dependencies required.

Tables:
  - pipeline_runs         : batch execution tracking
  - source_records        : raw ingested records
  - record_validation     : per-record validation classification
  - canonical_entities    : golden master records (CAN-XXXX)
  - canonical_mappings    : source_id -> canonical_id links
  - mapping_history       : audit trail of mapping changes
  - mapping_conflicts     : quarantined one-to-many email collisions
  - data_quality_rejects  : rejected/quarantined records
  - unresolved_mappings   : records missing sufficient identifiers
"""
import sqlite3
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BASE_DIR / "data" / "pipeline.db"


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Open (or create) the SQLite database and return a connection."""
    path = Path(db_path or DEFAULT_DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Optional[Path] = None) -> None:
    """Create all tables if they do not already exist."""
    conn = get_connection(db_path)
    with conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS pipeline_runs (
                run_id              TEXT PRIMARY KEY,
                source_file         TEXT,
                source_file_hash    TEXT,
                start_time          TEXT NOT NULL,
                end_time            TEXT,
                run_status          TEXT NOT NULL DEFAULT 'RUNNING',
                input_count         INTEGER NOT NULL DEFAULT 0,
                processed_count     INTEGER NOT NULL DEFAULT 0,
                new_entity_count    INTEGER NOT NULL DEFAULT 0,
                mapped_count        INTEGER NOT NULL DEFAULT 0,
                unresolved_count    INTEGER NOT NULL DEFAULT 0,
                rejected_count      INTEGER NOT NULL DEFAULT 0,
                duplicate_count     INTEGER NOT NULL DEFAULT 0,
                conflict_count      INTEGER NOT NULL DEFAULT 0,
                failure_reason      TEXT
            );

            CREATE TABLE IF NOT EXISTS source_records (
                source_record_id    INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id              TEXT NOT NULL,
                source_system       TEXT NOT NULL,
                source_id           TEXT,
                full_name           TEXT,
                email               TEXT,
                phone               TEXT,
                source_updated_at   TEXT,
                source_file         TEXT,
                ingested_at         TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES pipeline_runs(run_id)
            );

            CREATE INDEX IF NOT EXISTS ix_source_run ON source_records(run_id);
            CREATE INDEX IF NOT EXISTS ix_source_sys_id ON source_records(source_system, source_id);

            CREATE TABLE IF NOT EXISTS record_validation (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                source_record_id    INTEGER NOT NULL,
                run_id              TEXT NOT NULL,
                validation_status   TEXT NOT NULL,
                validation_reason   TEXT,
                FOREIGN KEY (source_record_id) REFERENCES source_records(source_record_id)
            );

            CREATE INDEX IF NOT EXISTS ix_val_run ON record_validation(run_id);

            CREATE TABLE IF NOT EXISTS canonical_entities (
                canonical_id        TEXT PRIMARY KEY,
                full_name           TEXT,
                normalized_email    TEXT,
                normalized_phone    TEXT,
                created_at          TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS ix_can_email ON canonical_entities(normalized_email);

            CREATE TABLE IF NOT EXISTS canonical_mappings (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                source_system       TEXT NOT NULL,
                source_id           TEXT NOT NULL,
                canonical_id        TEXT NOT NULL,
                match_type          TEXT NOT NULL,
                confidence_score    REAL,
                created_at          TEXT NOT NULL,
                updated_at          TEXT NOT NULL,
                FOREIGN KEY (canonical_id) REFERENCES canonical_entities(canonical_id)
            );

            CREATE INDEX IF NOT EXISTS ix_map_src ON canonical_mappings(source_system, source_id);

            CREATE TABLE IF NOT EXISTS mapping_history (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                source_system       TEXT NOT NULL,
                source_id           TEXT NOT NULL,
                old_canonical_id    TEXT,
                new_canonical_id    TEXT,
                change_reason       TEXT,
                changed_at          TEXT NOT NULL,
                run_id              TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS mapping_conflicts (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                source_record_id    INTEGER NOT NULL,
                run_id              TEXT NOT NULL,
                conflict_type       TEXT NOT NULL,
                conflict_details    TEXT,
                status              TEXT NOT NULL DEFAULT 'OPEN',
                detected_at         TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS data_quality_rejects (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                source_record_id    INTEGER NOT NULL,
                run_id              TEXT NOT NULL,
                rejection_reason    TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS unresolved_mappings (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                source_record_id    INTEGER NOT NULL,
                run_id              TEXT NOT NULL,
                reason              TEXT NOT NULL
            );
        """)
    conn.close()
    logger.info("SQLite schema initialized at %s", DEFAULT_DB_PATH)

