"""
Core Entity Resolution & Matching Engine.

Implements deterministic matching, conflict detection, and canonical golden record publishing:

1. Pre-Resolution Conflict Detection:
   - Detects shared emails among distinct individuals (different names/phones).
   - First colliding pair: 'email_collision'.
   - Subsequent occurrences: 'multiple_candidates'.
   - Quarantines conflicts in mapping_conflicts table.

2. Deterministic Matching (in priority order):
   - Pass 1: Exact normalized email match -> exact_email / exact_email_after_normalization.
   - Pass 2: Secondary rule match (Name + Phone) -> rule_name_phone.
   - Pass 3: New golden entity -> new.

3. Target Publishing & Audit History:
   - canonical_entities: golden master records.
   - canonical_mappings: source_id -> canonical_id links.
   - mapping_history: audit trail.
"""

import re
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import pandas as pd

from src.store import get_connection, DEFAULT_DB_PATH
from src.normalization import normalize_name, normalize_email, normalize_phone

logger = logging.getLogger(__name__)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_run_records_for_resolution(run_id: str, db_path: Optional[Path] = None) -> pd.DataFrame:
    conn = get_connection(db_path)
    try:
        rows = conn.execute("""
            SELECT s.source_record_id, s.run_id, s.source_system, s.source_id,
                   s.full_name, s.email, s.phone, s.source_updated_at,
                   v.validation_status, v.validation_reason
            FROM source_records s
            LEFT JOIN record_validation v ON s.source_record_id = v.source_record_id
            WHERE s.run_id = ?
            ORDER BY s.source_record_id
        """, (run_id,)).fetchall()
        return pd.DataFrame([dict(r) for r in rows])
    finally:
        conn.close()


def load_existing_canonical_entities(db_path: Optional[Path] = None) -> pd.DataFrame:
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT canonical_id, full_name, normalized_email, normalized_phone, created_at FROM canonical_entities"
        ).fetchall()
        return pd.DataFrame([dict(r) for r in rows])
    finally:
        conn.close()


def get_next_canonical_seq(db_path: Optional[Path] = None) -> int:
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT MAX(canonical_id) FROM canonical_entities WHERE canonical_id LIKE 'CAN-%'").fetchone()
        max_id = row[0] if row else None
        if max_id:
            m = re.search(r"CAN-(\d+)", str(max_id))
            if m:
                return int(m.group(1)) + 1
        return 1001
    finally:
        conn.close()


def detect_conflicts(df_valid: pd.DataFrame) -> Dict[int, Tuple[str, str]]:
    """
    Identify one-to-many email collisions and multiple candidate ambiguities.
    Returns {source_record_id: (conflict_type, conflict_details)}
    """
    conflicts: Dict[int, Tuple[str, str]] = {}
    if df_valid.empty:
        return conflicts

    email_groups: Dict[str, List[Dict[str, Any]]] = {}

    for _, row in df_valid.iterrows():
        email_norm = normalize_email(row["email"])
        if not email_norm:
            continue
        name_norm = normalize_name(row["full_name"])
        phone_norm = normalize_phone(row["phone"])
        item = {
            "source_record_id": int(row["source_record_id"]),
            "name": name_norm,
            "phone": phone_norm,
        }
        email_groups.setdefault(email_norm, []).append(item)

    for email, group in email_groups.items():
        if len(group) <= 1:
            continue
        # Detect distinct persons (different name OR phone)
        distinct_signatures = {(g["name"], g["phone"]) for g in group}
        if len(distinct_signatures) <= 1:
            continue  # Same person, not a collision

        for idx, member in enumerate(group):
            record_id = member["source_record_id"]
            if idx < 2:
                conflicts[record_id] = (
                    "email_collision",
                    f"Email '{email}' shared by {len(group)} distinct persons",
                )
            else:
                conflicts[record_id] = (
                    "multiple_candidates",
                    f"Email '{email}' already flagged as collision, additional record",
                )

    return conflicts


def resolve_batch(
    df_all: pd.DataFrame,
    run_id: str,
    existing_canonicals: Optional[pd.DataFrame] = None,
    starting_canonical_seq: Optional[int] = None,
    db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Execute deterministic entity resolution on a full batch.
    Works entirely in-memory using hash lookups — O(N) complexity.
    Returns resolved dict with reconciliation_results and counts.
    """
    if df_all.empty:
        return {
            "reconciliation_results": [],
            "new_canonical_entities": [],
            "canonical_mappings": [],
            "mapping_conflicts": [],
            "mapping_history": [],
            "new_entity_count": 0,
            "mapped_count": 0,
            "conflict_count": 0,
        }

    # Load existing golden records
    if existing_canonicals is None or existing_canonicals.empty:
        existing_canonicals = load_existing_canonical_entities(db_path) if db_path else pd.DataFrame()

    canonical_seq = starting_canonical_seq or get_next_canonical_seq(db_path)

    # Build in-memory inverted indexes
    email_index: Dict[str, str] = {}   # normalized_email -> canonical_id
    name_phone_index: Dict[Tuple[str, str], str] = {}  # (name, phone) -> canonical_id

    for _, ce in existing_canonicals.iterrows():
        if ce.get("normalized_email"):
            email_index[ce["normalized_email"]] = ce["canonical_id"]
        if ce.get("full_name") and ce.get("normalized_phone"):
            key = (normalize_name(ce["full_name"]), ce["normalized_phone"])
            if key[0] and key[1]:
                name_phone_index[key] = ce["canonical_id"]

    # Get valid records for conflict detection
    df_valid = df_all[df_all["validation_status"] == "VALID"].copy()
    conflicts = detect_conflicts(df_valid)

    reconciliation_results = []
    new_canonical_entities = []
    canonical_mappings = []
    mapping_conflicts_list = []
    mapping_history = []

    now = utc_now()

    for _, row in df_all.iterrows():
        record_id = int(row["source_record_id"])
        status = str(row.get("validation_status", "REJECTED"))
        reason = row.get("validation_reason")

        # Pass through non-valid records
        if status == "REJECTED":
            reconciliation_results.append({
                "source_record_id": record_id,
                "source_system": row.get("source_system"),
                "source_id": row.get("source_id"),
                "outcome": "REJECTED",
                "match_type": reason or "validation_failed",
                "canonical_id": None,
                "confidence_score": None,
            })
            continue

        if status == "DUPLICATE":
            reconciliation_results.append({
                "source_record_id": record_id,
                "source_system": row.get("source_system"),
                "source_id": row.get("source_id"),
                "outcome": "DUPLICATE",
                "match_type": "duplicate_source_key",
                "canonical_id": None,
                "confidence_score": None,
            })
            continue

        if status == "UNRESOLVED":
            reconciliation_results.append({
                "source_record_id": record_id,
                "source_system": row.get("source_system"),
                "source_id": row.get("source_id"),
                "outcome": "UNRESOLVED",
                "match_type": "no_identifiers",
                "canonical_id": None,
                "confidence_score": None,
            })
            continue

        # VALID record: check conflicts first
        if record_id in conflicts:
            conflict_type, conflict_details = conflicts[record_id]
            mapping_conflicts_list.append({
                "source_record_id": record_id,
                "run_id": run_id,
                "conflict_type": conflict_type,
                "conflict_details": conflict_details,
                "status": "OPEN",
                "detected_at": now,
            })
            reconciliation_results.append({
                "source_record_id": record_id,
                "source_system": row.get("source_system"),
                "source_id": row.get("source_id"),
                "outcome": "CONFLICT",
                "match_type": conflict_type,
                "canonical_id": None,
                "confidence_score": None,
            })
            continue

        # Normalize for matching
        norm_email = normalize_email(row.get("email"))
        norm_name = normalize_name(row.get("full_name"))
        norm_phone = normalize_phone(row.get("phone"))

        matched_canonical_id = None
        match_type = None
        confidence_score = None

        # Pass 1: Email match — distinguish exact vs after-normalization
        if norm_email and norm_email in email_index:
            raw_email = str(row.get("email", "")).strip()
            if raw_email.lower() == raw_email:  # Already lowercase = exact
                match_type = "exact_email"
                confidence_score = 100.0
            else:
                match_type = "exact_email_after_normalization"
                confidence_score = 98.0
            matched_canonical_id = email_index[norm_email]

        # Pass 2: Rule-based name + phone
        if not matched_canonical_id and norm_name and norm_phone:
            key = (norm_name, norm_phone)
            if key in name_phone_index:
                matched_canonical_id = name_phone_index[key]
                match_type = "rule_name_phone"
                confidence_score = 90.0

        # Pass 3: New entity
        if not matched_canonical_id:
            canonical_id = f"CAN-{canonical_seq}"
            canonical_seq += 1
            matched_canonical_id = canonical_id
            match_type = "new"
            confidence_score = 100.0

            new_canonical_entities.append({
                "canonical_id": canonical_id,
                "full_name": row.get("full_name"),
                "normalized_email": norm_email,
                "normalized_phone": norm_phone,
                "created_at": now,
            })

            # Update indexes for subsequent records in same batch
            if norm_email:
                email_index[norm_email] = canonical_id
            if norm_name and norm_phone:
                name_phone_index[(norm_name, norm_phone)] = canonical_id

            outcome = "NEW_ENTITY"
            mapping_history.append({
                "source_system": row.get("source_system"),
                "source_id": row.get("source_id"),
                "old_canonical_id": None,
                "new_canonical_id": canonical_id,
                "change_reason": "NEW_ENTITY_CREATED",
                "changed_at": now,
                "run_id": run_id,
            })
        else:
            outcome = "MAPPED"
            mapping_history.append({
                "source_system": row.get("source_system"),
                "source_id": row.get("source_id"),
                "old_canonical_id": None,
                "new_canonical_id": matched_canonical_id,
                "change_reason": f"MATCHED_{match_type.upper()}",
                "changed_at": now,
                "run_id": run_id,
            })

        canonical_mappings.append({
            "source_system": row.get("source_system"),
            "source_id": row.get("source_id"),
            "canonical_id": matched_canonical_id,
            "match_type": match_type,
            "confidence_score": confidence_score,
            "created_at": now,
            "updated_at": now,
        })

        reconciliation_results.append({
            "source_record_id": record_id,
            "source_system": row.get("source_system"),
            "source_id": row.get("source_id"),
            "outcome": outcome,
            "match_type": match_type,
            "canonical_id": matched_canonical_id,
            "confidence_score": confidence_score,
        })

    new_entity_count = sum(1 for r in reconciliation_results if r["outcome"] == "NEW_ENTITY")
    mapped_count = sum(1 for r in reconciliation_results if r["outcome"] == "MAPPED")
    conflict_count = sum(1 for r in reconciliation_results if r["outcome"] == "CONFLICT")

    return {
        "reconciliation_results": reconciliation_results,
        "new_canonical_entities": new_canonical_entities,
        "canonical_mappings": canonical_mappings,
        "mapping_conflicts": mapping_conflicts_list,
        "mapping_history": mapping_history,
        "new_entity_count": new_entity_count,
        "mapped_count": mapped_count,
        "conflict_count": conflict_count,
    }


def persist_resolution_results(resolved: Dict[str, Any], run_id: str, db_path: Optional[Path] = None):
    """Commit resolved entities, mappings, history, and conflicts to SQLite."""
    conn = get_connection(db_path)
    now = utc_now()
    try:
        with conn:
            # 1. New golden entities
            for e in resolved["new_canonical_entities"]:
                conn.execute(
                    "INSERT OR IGNORE INTO canonical_entities (canonical_id, full_name, normalized_email, normalized_phone, created_at) VALUES (?,?,?,?,?)",
                    (e["canonical_id"], e["full_name"], e["normalized_email"], e["normalized_phone"], e["created_at"]),
                )
            # 2. Source-to-canonical mappings
            for m in resolved["canonical_mappings"]:
                conn.execute(
                    "INSERT INTO canonical_mappings (source_system, source_id, canonical_id, match_type, confidence_score, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                    (m["source_system"], m["source_id"], m["canonical_id"], m["match_type"], m["confidence_score"], m["created_at"], m["updated_at"]),
                )
            # 3. Conflicts
            for c in resolved["mapping_conflicts"]:
                conn.execute(
                    "INSERT INTO mapping_conflicts (source_record_id, run_id, conflict_type, conflict_details, status, detected_at) VALUES (?,?,?,?,?,?)",
                    (c["source_record_id"], c["run_id"], c["conflict_type"], c["conflict_details"], c["status"], c["detected_at"]),
                )
            # 4. History
            for h in resolved["mapping_history"]:
                conn.execute(
                    "INSERT INTO mapping_history (source_system, source_id, old_canonical_id, new_canonical_id, change_reason, changed_at, run_id) VALUES (?,?,?,?,?,?,?)",
                    (h["source_system"], h["source_id"], h["old_canonical_id"], h["new_canonical_id"], h["change_reason"], h["changed_at"], h["run_id"]),
                )
            # 5. Update pipeline run status
            conn.execute(
                "UPDATE pipeline_runs SET run_status='SUCCESS', new_entity_count=?, mapped_count=?, conflict_count=?, end_time=? WHERE run_id=?",
                (resolved["new_entity_count"], resolved["mapped_count"], resolved["conflict_count"], now, run_id),
            )
    finally:
        conn.close()
    logger.info("Persisted resolution for run %s: %d new, %d mapped, %d conflicts",
                run_id, resolved["new_entity_count"], resolved["mapped_count"], resolved["conflict_count"])


def run_resolution(run_id: str, db_path: Optional[Path] = None) -> pd.DataFrame:
    """Execute resolution stage and return reconciliation DataFrame."""
    logger.info("Running entity resolution for run %s", run_id)
    df = load_run_records_for_resolution(run_id, db_path)
    if df.empty:
        logger.warning("No records for run %s", run_id)
        return pd.DataFrame()
    resolved = resolve_batch(df_all=df, run_id=run_id, db_path=db_path)
    persist_resolution_results(resolved, run_id, db_path)
    return pd.DataFrame(resolved["reconciliation_results"])
