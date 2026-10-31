# Entity Resolution Pipeline

[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Storage](https://img.shields.io/badge/storage-SQLite%20(built--in)-green.svg)](https://docs.python.org/3/library/sqlite3.html)
[![Tests](https://img.shields.io/badge/tests-28%20passed-brightgreen.svg)](https://docs.pytest.org/)
[![Throughput](https://img.shields.io/badge/throughput-~9%2C000%20rec%2Fsec-success.svg)](src/benchmark.py)

A production-quality, deterministic Data Engineering solution that maps source identifiers to canonical golden-record IDs using **exact and rule-based matching**, detects **one-to-many conflicts**, retains **full mapping history**, and exposes **unresolved mappings** — all with zero external service dependencies (pure SQLite).

---

## Table of Contents

1. [Business Context & Problem Statement](#1-business-context--problem-statement)
2. [Architecture & Pipeline Workflow](#2-architecture--pipeline-workflow)
3. [Data Dictionary & Entity Relationships](#3-data-dictionary--entity-relationships)
4. [Matching Rules & Business Logic](#4-matching-rules--business-logic)
5. [Setup & Installation](#5-setup--installation)
6. [Running the Pipeline](#6-running-the-pipeline)
7. [Running Tests](#7-running-tests)
8. [Generating Synthetic Data](#8-generating-synthetic-data)
9. [Performance Benchmarking](#9-performance-benchmarking)
10. [Idempotency & Rerun Behavior](#10-idempotency--rerun-behavior)
11. [Design Choices & Trade-offs](#11-design-choices--trade-offs)
12. [Known Limitations & Next Steps](#12-known-limitations--next-steps)
13. [Project Structure](#13-project-structure)
14. [Naming Conventions](#14-naming-conventions)

---

## 1. Business Context & Problem Statement

Enterprises ingest customer records from fragmented, siloed platforms (CRM, E-Commerce, Marketing, Support) where the same individual appears under different keys, formatting variations, or conflicting identifiers.

### Core Objectives

| Objective | Implementation |
| :--- | :--- |
| **Map source IDs → canonical IDs** | Exact email + rule-based (Name + Phone) matching |
| **Detect one-to-many conflicts** | Email collision detection; quarantine to `mapping_conflicts` |
| **Retain mapping history** | Every mapping event appended to `mapping_history` |
| **Expose unresolved mappings** | Records with no email and no phone go to `unresolved_mappings` |
| **Mathematical reconciliation** | Input = New + Mapped + Conflicts + Unresolved + Duplicates + Rejects |

---

## 2. Architecture & Pipeline Workflow

```
Raw CSV Input
     │
     ▼
┌──────────────────────────────────────────────────────┐
│  STEP 1 — INGESTION  (src/ingestion.py)               │
│  • SHA-256 file hash for idempotency                  │
│  • Register run in pipeline_runs (status=RUNNING)     │
│  • Bulk-insert raw records into source_records        │
└─────────────────────────┬────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────┐
│  STEP 2 — VALIDATION  (src/validation.py)             │
│  • Check: source_system present                       │
│  • Check: source_id present                           │
│  • Check: email format (RFC-style regex)              │
│  • Check: duplicate source keys (identical/conflict)  │
│  • Check: no email AND no phone → UNRESOLVED          │
│  • Persist to: record_validation                      │
│  • Quarantine: data_quality_rejects, unresolved_mappings│
└─────────────────────────┬────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────┐
│  STEP 3 — RESOLUTION  (src/resolution.py)             │
│  • Pre-pass: detect email collisions → CONFLICT       │
│  • Pass 1a: exact normalized email match              │
│  • Pass 1b: case/whitespace-normalized email match    │
│  • Pass 2:  name + phone rule match                   │
│  • Pass 3:  mint new canonical ID (CAN-XXXX)          │
│  • Persist: canonical_entities, canonical_mappings,   │
│             mapping_history, mapping_conflicts        │
└─────────────────────────┬────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────┐
│  STEP 4 — RECONCILIATION  (src/reconciliation.py)     │
│  • Verify: Input = sum of all outcome categories      │
│  • Export: data/output/resolution_results_{run}.csv   │
│  • Report: reports/reconciliation_report_{run}.md     │
│  • Update: pipeline_runs (status=SUCCESS)             │
└─────────────────────────┬────────────────────────────┘
                          │
                          ▼
              ✅ BALANCED — 100% Accounted
```

---

## 3. Data Dictionary & Entity Relationships

### `pipeline_runs` — Batch execution tracking

| Column | Type | Nullable | Description |
| :--- | :--- | :---: | :--- |
| `run_id` | TEXT (UUID) | No | Primary key; stable UUID per batch |
| `source_file` | TEXT | Yes | Absolute path of input CSV |
| `source_file_hash` | TEXT | Yes | SHA-256 of input file for idempotency |
| `start_time` | TEXT (ISO-8601) | No | UTC start timestamp |
| `end_time` | TEXT (ISO-8601) | Yes | UTC end timestamp |
| `run_status` | TEXT | No | `RUNNING` → `SUCCESS` / `FAILED` |
| `input_count` | INT | No | Total raw records ingested |
| `new_entity_count` | INT | No | Golden records minted this run |
| `mapped_count` | INT | No | Records matched to existing canonical |
| `conflict_count` | INT | No | Records quarantined as conflicts |
| `unresolved_count` | INT | No | Records with no identifiers |
| `rejected_count` | INT | No | Records failing data quality rules |
| `duplicate_count` | INT | No | Duplicate source keys |
| `failure_reason` | TEXT | Yes | Error message if status=FAILED |

### `source_records` — Raw staging

| Column | Type | Description |
| :--- | :--- | :--- |
| `source_record_id` | INTEGER PK | Auto-incrementing surrogate key |
| `run_id` | TEXT FK | Links to `pipeline_runs` |
| `source_system` | TEXT | Source origin (CRM, ECOM, MARKETING…) |
| `source_id` | TEXT | Natural key from source system |
| `full_name` | TEXT | Person's name (raw) |
| `email` | TEXT | Email (raw, may be malformed) |
| `phone` | TEXT | Phone number (raw) |
| `source_updated_at` | TEXT | ISO-8601 timestamp from source |
| `source_file` | TEXT | Source filename for lineage |
| `ingested_at` | TEXT | UTC time record was staged |

### `canonical_entities` — Golden master records

| Column | Type | Description |
| :--- | :--- | :--- |
| `canonical_id` | TEXT PK | Stable golden ID (`CAN-1001`, `CAN-1002`…) |
| `full_name` | TEXT | Original name at time of creation |
| `normalized_email` | TEXT | Lowercased, stripped email |
| `normalized_phone` | TEXT | 10-digit phone digits only |
| `created_at` | TEXT | UTC ISO-8601 timestamp |

### `canonical_mappings` — Source → Golden links

| Column | Type | Description |
| :--- | :--- | :--- |
| `source_system` + `source_id` | Composite | FK to source identity |
| `canonical_id` | TEXT FK | Links to `canonical_entities` |
| `match_type` | TEXT | How the match was made (see §4) |
| `confidence_score` | REAL | 100.0 / 98.0 / 90.0 |

### `mapping_history` — Audit trail

Every assignment event is appended — never overwritten. Supports point-in-time reconstruction.

### `mapping_conflicts` — Quarantine for one-to-many collisions

| Column | Description |
| :--- | :--- |
| `conflict_type` | `email_collision` or `multiple_candidates` |
| `conflict_details` | Human-readable description |
| `status` | `OPEN` (awaiting operator review) |

### `data_quality_rejects` / `unresolved_mappings`

Fully traceable via `source_record_id` back to the original staged record.

---

## 4. Matching Rules & Business Logic

Resolution applies rules in strict priority order:

| Priority | Match Type | Trigger | Confidence |
| :---: | :--- | :--- | :---: |
| 0 | `email_collision` | Multiple distinct persons share an email | — CONFLICT |
| 0 | `multiple_candidates` | Third+ person on a colliding email | — CONFLICT |
| 1 | `exact_email` | `normalize(raw_email)` == existing canonical email; raw was already lowercase | 100.0% |
| 2 | `exact_email_after_normalization` | Matches after lowercasing/trimming | 98.0% |
| 3 | `rule_name_phone` | `normalize(name)` + `normalize(phone)` match an existing canonical | 90.0% |
| 4 | `new` | No match found → mint `CAN-XXXX` | 100.0% |

**Validation rules (in order — first failure wins):**

1. `source_system` must be present → else `REJECTED / missing_source_system`
2. `source_id` must be present → else `REJECTED / missing_source_id`
3. Email, if present, must pass RFC regex → else `REJECTED / invalid_email`
4. Duplicate `(source_system, source_id)` key → `DUPLICATE` (identical) or `REJECTED / conflicting_duplicate_source_key`
5. No valid email AND no phone → `UNRESOLVED / no_identifiers`

---

## 5. Setup & Installation

**Prerequisites:** Python 3.10+ only. No database server, no ODBC driver, no cloud credentials required.

```bash
# 1. Clone and enter project
git clone <repo-url>
cd entity-resolution-pipeline

# 2. Create virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
```

That's it. The SQLite database (`data/pipeline.db`) is created automatically on first run.

---

## 6. Running the Pipeline

### Default run (13-record sample)

```bash
python run_pipeline.py
```

### With options

```bash
# Force re-process the same file (bypass idempotency)
python run_pipeline.py --force

# Custom input file
python run_pipeline.py --input data/input/synthetic_records.csv

# Custom database path (useful for isolated environments)
python run_pipeline.py --db data/my_test.db

# Custom output directories
python run_pipeline.py --output-dir data/output --report-dir reports

# All options at once
python run_pipeline.py --input data/input/synthetic_records.csv --force --db data/run.db
```

### As a Python module

```bash
python -m src --input data/input/source_records.csv --force
```

### Expected output (on a clean database)

```
Run ID              : <uuid>
Elapsed Time        : 0.05 s
Reconciliation      : ✅ BALANCED
Total Input         : 13
  → New Entities    : 3
  → Mapped          : 3
  → Conflicts       : 3
  → Unresolved      : 1
  → Duplicates      : 1
  → Rejects         : 2
Benchmark Accuracy  : 13/13 (100.0%)
```

### Outputs

| File | Description |
| :--- | :--- |
| `data/pipeline.db` | SQLite database (all state) |
| `data/output/resolution_results_{run_id}.csv` | Per-run resolved records |
| `data/output/resolution_results.csv` | Latest run results (overwritten) |
| `reports/reconciliation_report_{run_id}.md` | Full Markdown audit report |
| `reports/latest_reconciliation.md` | Latest report (overwritten) |

---

## 7. Running Tests

```bash
# All 28 tests
python run_tests.py

# Or directly with pytest
pytest tests/ -v

# Single test module
pytest tests/test_resolution.py -v
```

### Test Coverage (28 tests)

| Module | Tests | What's Covered |
| :--- | :---: | :--- |
| `test_end_to_end.py` | 1 | Full vertical slice; 100% benchmark accuracy vs expected_results.csv |
| `test_normalization.py` | 13 | Email lowercase/trim/null; name collapse/title-case/null; phone digits/prefix/null |
| `test_resolution.py` | 7 | New entity, exact email, normalized email, name+phone rule, email collision, multiple_candidates, empty batch |
| `test_validation.py` | 7 | Missing source_system, missing source_id, invalid email, no_identifiers, identical duplicate, conflicting duplicate, empty DataFrame, schema mismatch |

All tests are **pure in-memory** — no database connection required.

---

## 8. Generating Synthetic Data

### Small scalable dataset

```bash
# 1,000 records (default)
python -m src.data_generator

# 50,000 records
python -m src.data_generator --count 50000 --output data/input/synthetic_50k.csv

# Reproducible with fixed seed
python -m src.data_generator --count 10000 --seed 42 --output data/input/synthetic_10k.csv
```

### Multi-source (CRM + Billing JSON + ERP)

```bash
python -m src.multi_source_generator --population 100
```

Generates:
- `data/input/crm_customers.csv`
- `data/input/billing_accounts.json`
- `data/input/erp_clients.csv`
- `data/expected/multi_source_expected.csv` (ground truth)

**Generated data always includes:**
- Normal exact email matches across systems
- Normalized email matches (case/whitespace noise)
- Rule-based name + phone matches
- Email collisions (shared household emails)
- Missing fields, malformed emails, duplicates, no-identifier records
- Fixed random seed (42) for full reproducibility

---

## 9. Performance Benchmarking

```bash
# Default: 500, 2500, 10000 records
python -m src.benchmark

# Custom scales
python -m src.benchmark --scales 1000 10000 100000
```

### Empirical Results (Python 3.13, single-core)

| Records | Duration | Throughput | Validation | Resolution |
| :---: | :---: | :---: | :---: | :---: |
| 500 | 0.067 s | 7,500 rec/s | 0.026 s | 0.037 s |
| 2,500 | 0.255 s | 9,820 rec/s | 0.108 s | 0.139 s |
| 10,000 | 1.084 s | 9,223 rec/s | 0.430 s | 0.622 s |

### Key Optimizations

1. **O(N) in-memory hash indexes**: Email → canonical_id and (name, phone) → canonical_id dictionaries eliminate O(N²) pairwise comparisons.
2. **Vectorized normalization**: `pandas.Series.apply()` with pre-compiled regex for batch email/phone normalization.
3. **SQLite WAL mode**: Write-Ahead Logging allows concurrent reads during writes, reducing lock contention on batch inserts.

---

## 10. Idempotency & Rerun Behavior

| Scenario | Behavior |
| :--- | :--- |
| **Same file, same content** | SHA-256 hash matched → run SKIPPED, existing `run_id` returned |
| **Same file, force flag** | `--force` bypasses hash check → new `run_id` created, full pipeline re-runs |
| **Different file** | New hash → new `run_id`, processed independently |
| **Validation already done** | `run_validation` checks `record_validation` table count → skips if > 0 |
| **DB deleted, same file** | New run created (hash not found) → clean slate |
| **Partial failure** | `pipeline_runs.run_status` stays `RUNNING`; next `--force` re-runs |

```bash
# Reset and start clean
del data\pipeline.db
python run_pipeline.py
```

---

## 11. Design Choices & Trade-offs

### Deterministic vs Probabilistic Matching

**Choice:** Rule-based exact matching (email + name/phone) instead of probabilistic scoring (Jaro-Winkler, Fellegi-Sunter).

**Trade-off:** Zero false-positive merges and fully auditable decisions. Cost: typos (`sachin.jadhav` vs `sachin.jadhv`) create separate entities rather than fuzzy-merging. Acceptable at 0–3yr level; probabilistic matching would be the next step.

### Explicit Conflict Quarantine vs Blind Merge

**Choice:** When multiple distinct persons share an email, neither is assigned a canonical ID. Both are quarantined to `mapping_conflicts` with `status=OPEN` for operator review.

**Trade-off:** Prevents golden-record corruption at the cost of requiring a manual resolution step. The alternative (first-seen wins) silently corrupts identity data.

### SQLite as Local Storage

**Choice:** Python's built-in `sqlite3` instead of requiring SQL Server / PostgreSQL.

**Trade-off:** Zero setup friction, reproducible from a clean environment, portable single-file database. SQLite is not suitable for multi-writer concurrent pipelines at production scale — MSSQL/PostgreSQL support is available via the legacy `src/db_connection.py` + `database/schema.sql` (kept for reference).

### Conservation Equation

Every input record maps to exactly one outcome category:

```
Input = NEW_ENTITY + MAPPED + CONFLICT + UNRESOLVED + DUPLICATE + REJECTED
```

If `discrepancy ≠ 0` the pipeline reports `DISCREPANCY DETECTED` and the reconciliation report shows the gap.

---

## 12. Known Limitations & Next Steps

| Limitation | Suggested Next Step |
| :--- | :--- |
| Typos create separate entities | Add phonetic blocking (Double Metaphone) or Levenshtein distance threshold |
| Single-node, single-threaded | Partition by email domain; run blocks in parallel with Ray or Dask |
| SQLite not suitable for >10 concurrent writers | Swap `src/store.py` for `src/db_connection.py` (MSSQL) for production |
| No REST API | Expose `run_pipeline()` via FastAPI for operator integrations |
| Conflict resolution is manual | Build a simple web UI or CLI to review and resolve `OPEN` conflicts |
| No CDC / streaming support | Add Kafka consumer to process record-at-a-time with micro-batching |

---

## 13. Project Structure

```
entity-resolution-pipeline/
├── src/
│   ├── __init__.py
│   ├── __main__.py           # python -m src entrypoint
│   ├── store.py              # SQLite schema + connection (built-in sqlite3)
│   ├── ingestion.py          # SHA-256 idempotency + CSV loader + staging
│   ├── validation.py         # 5 data-quality rules + quarantine
│   ├── normalization.py      # Email / name / phone normalization functions
│   ├── resolution.py         # Conflict detection + matching + entity minting
│   ├── reconciliation.py     # Conservation check + CSV + Markdown report
│   ├── pipeline.py           # Orchestrator (Steps 1–4) + CLI
│   ├── data_generator.py     # Scalable synthetic dataset generator
│   ├── multi_source_generator.py # CRM/Billing/ERP multi-format generator
│   ├── benchmark.py          # Performance measurement across scales
│   └── db_connection.py      # Legacy MSSQL connector (optional, not required)
│
├── tests/
│   ├── conftest.py           # Shared pytest fixtures
│   ├── test_end_to_end.py    # Full vertical slice benchmark test
│   ├── test_normalization.py # 13 unit tests for normalization
│   ├── test_resolution.py    # 7 unit tests for resolution logic
│   └── test_validation.py    # 7 unit tests for validation rules
│
├── data/
│   ├── input/
│   │   ├── source_records.csv        # 13-record hand-crafted sample
│   │   ├── crm_customers.csv         # Multi-source: CRM
│   │   ├── billing_accounts.json     # Multi-source: Billing
│   │   └── erp_clients.csv           # Multi-source: ERP
│   ├── expected/
│   │   ├── expected_results.csv      # Ground truth for benchmark test
│   │   └── multi_source_expected.csv # Multi-source ground truth
│   ├── output/                       # Generated per-run CSVs
│   ├── quarantine/                   # (reserved)
│   └── pipeline.db                   # SQLite database (auto-created)
│
├── database/
│   └── schema.sql                    # MSSQL schema (reference / optional)
│
├── config/
│   └── source_config.yaml            # Source system field mappings
│
├── reports/                          # Generated Markdown audit reports
│
├── run_pipeline.py                   # Convenience runner script
├── run_tests.py                      # Convenience test runner
├── setup.py                          # pip install -e . support
├── requirements.txt                  # Runtime dependencies
├── .env                              # MSSQL credentials (optional)
└── .gitignore
```

---

## 14. Naming Conventions

| Convention | Applied To | Example |
| :--- | :--- | :--- |
| `snake_case` | All table names, column names, Python identifiers | `source_record_id`, `canonical_id` |
| `CAN-XXXX` | Canonical golden record IDs | `CAN-1001`, `CAN-1042` |
| UUID v4 | Run IDs | `7c862438-a892-46d7-99e6-751cb8c31b6a` |
| ISO-8601 UTC | All timestamps | `2026-10-31T05:46:37Z` |
| `run_id` column | Every operational table | Enables per-run filtering and audit |
| `source_file` | `pipeline_runs`, `source_records` | Full path for lineage tracing |
| Outcome labels | UPPERCASE | `NEW_ENTITY`, `MAPPED`, `CONFLICT`, `UNRESOLVED`, `DUPLICATE`, `REJECTED` |
| Match type labels | `snake_case` | `exact_email`, `rule_name_phone`, `email_collision` |

---

## Quick Reference

```bash
# From clean environment
pip install -r requirements.txt

# Run pipeline on sample data
python run_pipeline.py

# Force rerun
python run_pipeline.py --force

# Run on synthetic data (generate first)
python -m src.data_generator --count 10000 --output data/input/synthetic_10k.csv
python run_pipeline.py --input data/input/synthetic_10k.csv --db data/synthetic.db

# All tests
python run_tests.py

# Benchmark
python -m src.benchmark --scales 500 5000 50000
```
